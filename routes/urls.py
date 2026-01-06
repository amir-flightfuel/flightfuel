from django.urls import path, include
from django.shortcuts import render
from django.http import JsonResponse
from rest_framework.routers import DefaultRouter
from .views import (
    WaypointViewSet, AirwayViewSet, AirwaySegmentViewSet,
    RouteViewSet, FlightInformationRegionViewSet,
    AirportGeoJSON, WaypointGeoJSON, FIRGeoJSON,
    CalculateRoute, SaveRouteAPI, SaveAsRouteAPI,
    GetRoutesAPI, GetRouteDetailAPI, DeleteRouteAPI, ImportRouteAPI,
    RouteSearchAPI, dashboard_view,
    EnhancedSaveRouteAPI, AdvancedDeleteRouteAPI, RestoreRouteAPI  # New APIs added
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
    # 0. MAIN PAGES (Dashboard)
    path('', dashboard_view, name='home'),
    path('dashboard/', dashboard_view, name='dashboard'),
    
    # 1. Router URLs (for DRF ViewSets)
    path('api/', include(router.urls)),
    
    # 2. GeoJSON APIs (for Frontend Map Display)
    path('api/airports/', AirportGeoJSON.as_view(), name='airports_geojson'),
    path('api/waypoints/', WaypointGeoJSON.as_view(), name='waypoints_geojson'),
    path('api/fir-geojson/', FIRGeoJSON.as_view(), name='fir_geojson'),
    
    # 3. Route Management APIs (Core)
    path('api/calculate-route/', CalculateRoute.as_view(), name='calculate_route'),
    
    # 3.1 Save APIs (Multiple options - With Conflict Resolution Support)
    path('api/save-route/', SaveRouteAPI.as_view(), name='save_route'),  # Legacy - Simple save
    path('api/save-route-as/', SaveAsRouteAPI.as_view(), name='save_route_as'),  # Legacy - Save as new
    path('api/enhanced-save-route/', EnhancedSaveRouteAPI.as_view(), name='enhanced_save_route'),  # New with popup support
    
    # 3.2 Get/View APIs
    path('api/get-routes/', GetRoutesAPI.as_view(), name='get_routes'),
    path('api/get-route/<int:route_id>/', GetRouteDetailAPI.as_view(), name='get_route_detail'),
    
    # 3.3 Delete APIs (With soft/hard delete options)
    path('api/delete-route/<int:route_id>/', DeleteRouteAPI.as_view(), name='delete_route'),  # Legacy - Hard delete
    path('api/advanced-delete-route/<int:route_id>/', AdvancedDeleteRouteAPI.as_view(), name='advanced_delete_route'),  # New with soft/hard options
    path('api/restore-route/<int:route_id>/', RestoreRouteAPI.as_view(), name='restore_route'),  # New restore API
    
    # 3.4 Import API
    path('api/import-route/', ImportRouteAPI.as_view(), name='import_route'),
    
    # 4. Route Search APIs
    path('api/route-search/', RouteSearchAPI.as_view(), name='route_search'),
    
    # 5. Airport Search API (IATA to ICAO conversion)
    path('api/airports/search/', RouteViewSet.as_view({'get': 'search_airport'}), name='airport_search'),
    
    # 6. Route Export APIs
    path('api/export-route/<int:route_id>/', RouteViewSet.as_view({'get': 'export_route'}), name='export_route'),
    
    # 7. Route Versioning APIs
    path('api/route-versions/<int:route_id>/', RouteViewSet.as_view({'get': 'get_versions'}), name='route_versions'),
    path('api/restore-version/<int:version_id>/', RouteViewSet.as_view({'post': 'restore_version'}), name='restore_version'),
    
    # 8. Statistics & Analytics APIs
    path('api/route-stats/', RouteViewSet.as_view({'get': 'get_stats'}), name='route_stats'),
    path('api/popular-routes/', RouteViewSet.as_view({'get': 'popular_routes'}), name='popular_routes'),
    
    # 9. Health/Status API (for monitoring)
    path('api/health/', lambda request: JsonResponse({'status': 'healthy', 'service': 'FlightFuel API'}), name='health_check'),
    
    # 10. User-specific APIs
    path('api/my-routes/', RouteViewSet.as_view({'get': 'my_routes'}), name='my_routes'),
    path('api/shared-routes/', RouteViewSet.as_view({'get': 'shared_routes'}), name='shared_routes'),
    
    # 11. Route Validation APIs
    path('api/validate-route/', RouteViewSet.as_view({'post': 'validate_route'}), name='validate_route'),
    path('api/check-conflicts/', RouteViewSet.as_view({'post': 'check_conflicts'}), name='check_conflicts'),
    
    # 12. Route Optimization APIs
    path('api/optimize-route/', RouteViewSet.as_view({'post': 'optimize_route'}), name='optimize_route'),
    path('api/calculate-fuel/', RouteViewSet.as_view({'post': 'calculate_fuel'}), name='calculate_fuel'),
    
    # 13. FIR/Airspace APIs
    path('api/fir-intersections/', RouteViewSet.as_view({'post': 'fir_intersections'}), name='fir_intersections'),
    path('api/airspace-restrictions/', RouteViewSet.as_view({'get': 'airspace_restrictions'}), name='airspace_restrictions'),
    
    # 14. Waypoint/Airport Lookup APIs
    path('api/lookup-waypoint/<str:identifier>/', RouteViewSet.as_view({'get': 'lookup_waypoint'}), name='lookup_waypoint'),
    path('api/nearby-airports/', RouteViewSet.as_view({'get': 'nearby_airports'}), name='nearby_airports'),
    
    # 15. Batch Operations APIs
    path('api/bulk-delete-routes/', RouteViewSet.as_view({'post': 'bulk_delete'}), name='bulk_delete_routes'),
    path('api/bulk-export-routes/', RouteViewSet.as_view({'post': 'bulk_export'}), name='bulk_export_routes'),
    
    # 16. Template Routes APIs
    path('api/template-routes/', RouteViewSet.as_view({'get': 'template_routes'}), name='template_routes'),
    path('api/save-as-template/<int:route_id>/', RouteViewSet.as_view({'post': 'save_as_template'}), name='save_as_template'),
    
    # 17. Route Comparison APIs
    path('api/compare-routes/', RouteViewSet.as_view({'post': 'compare_routes'}), name='compare_routes'),
    
    # 18. Backup/Restore APIs
    path('api/backup-routes/', RouteViewSet.as_view({'get': 'backup_routes'}), name='backup_routes'),
    path('api/restore-backup/', RouteViewSet.as_view({'post': 'restore_backup'}), name='restore_backup'),
    
    # 19. Audit Log APIs
    path('api/route-audit/<int:route_id>/', RouteViewSet.as_view({'get': 'route_audit'}), name='route_audit'),
    path('api/user-activity/', RouteViewSet.as_view({'get': 'user_activity'}), name='user_activity'),
    
    # 20. Collaboration APIs
    path('api/share-route/<int:route_id>/', RouteViewSet.as_view({'post': 'share_route'}), name='share_route'),
    path('api/unshare-route/<int:route_id>/<int:user_id>/', RouteViewSet.as_view({'delete': 'unshare_route'}), name='unshare_route'),
    path('api/route-comments/<int:route_id>/', RouteViewSet.as_view({'get': 'get_comments', 'post': 'add_comment'}), name='route_comments'),
    
    # 21. Integration APIs
    path('api/export-fpl/<int:route_id>/', RouteViewSet.as_view({'get': 'export_fpl'}), name='export_fpl'),
    path('api/import-fpl/', RouteViewSet.as_view({'post': 'import_fpl'}), name='import_fpl'),
    path('api/export-gpx/<int:route_id>/', RouteViewSet.as_view({'get': 'export_gpx'}), name='export_gpx'),
    path('api/export-kml/<int:route_id>/', RouteViewSet.as_view({'get': 'export_kml'}), name='export_kml'),
    
    # 22. Search Enhancement APIs
    path('api/search-suggestions/', RouteViewSet.as_view({'get': 'search_suggestions'}), name='search_suggestions'),
    path('api/advanced-route-search/', RouteViewSet.as_view({'post': 'advanced_search'}), name='advanced_route_search'),
    
    # 23. Map Data APIs
    path('api/map-bounds/', RouteViewSet.as_view({'get': 'map_bounds'}), name='map_bounds'),
    path('api/airway-segments-geojson/', RouteViewSet.as_view({'get': 'airway_segments_geojson'}), name='airway_segments_geojson'),
    
    # 24. Weather Integration APIs
    path('api/route-weather/<int:route_id>/', RouteViewSet.as_view({'get': 'route_weather'}), name='route_weather'),
    path('api/weather-alerts/', RouteViewSet.as_view({'get': 'weather_alerts'}), name='weather_alerts'),
    
    # 25. Notification APIs
    path('api/route-notifications/', RouteViewSet.as_view({'get': 'route_notifications'}), name='route_notifications'),
    path('api/mark-notification-read/<int:notification_id>/', RouteViewSet.as_view({'post': 'mark_notification_read'}), name='mark_notification_read'),
    
    # 26. Admin/Management APIs
    path('api/admin/routes/', RouteViewSet.as_view({'get': 'admin_routes'}), name='admin_routes'),
    path('api/admin/cleanup/', RouteViewSet.as_view({'post': 'admin_cleanup'}), name='admin_cleanup'),
    path('api/admin/stats/', RouteViewSet.as_view({'get': 'admin_stats'}), name='admin_stats'),
    
    # 27. System Configuration APIs
    path('api/config/', RouteViewSet.as_view({'get': 'get_config'}), name='get_config'),
    path('api/config/update/', RouteViewSet.as_view({'post': 'update_config'}), name='update_config'),
    
    # 28. Custom Reports APIs
    path('api/reports/routes-by-date/', RouteViewSet.as_view({'get': 'routes_by_date'}), name='routes_by_date'),
    path('api/reports/routes-by-user/', RouteViewSet.as_view({'get': 'routes_by_user'}), name='routes_by_user'),
    path('api/reports/routes-by-aircraft/', RouteViewSet.as_view({'get': 'routes_by_aircraft'}), name='routes_by_aircraft'),
    
    # 29. Mobile App APIs
    path('api/mobile/routes/', RouteViewSet.as_view({'get': 'mobile_routes'}), name='mobile_routes'),
    path('api/mobile/sync/', RouteViewSet.as_view({'post': 'mobile_sync'}), name='mobile_sync'),
    
    # 30. Webhook/Integration APIs
    path('api/webhook/route-updated/', RouteViewSet.as_view({'post': 'route_updated_webhook'}), name='route_updated_webhook'),
    path('api/webhook/route-deleted/', RouteViewSet.as_view({'post': 'route_deleted_webhook'}), name='route_deleted_webhook'),
]

# ==================== ERROR HANDLERS ====================
handler404 = 'flightfuel.views.custom_404'
handler500 = 'flightfuel.views.custom_500'

# ==================== DOCUMENTATION ====================
"""
API Endpoints Documentation:

CORE FUNCTIONALITY:
1. Route Management:
   - GET    /api/get-routes/                 # List all routes
   - GET    /api/get-route/<id>/             # Get route details
   - POST   /api/save-route/                 # Save new route (legacy)
   - POST   /api/enhanced-save-route/        # Save with conflict resolution
   - DELETE /api/delete-route/<id>/          # Delete route (hard)
   - DELETE /api/advanced-delete-route/<id>/ # Delete with options
   - POST   /api/restore-route/<id>/         # Restore soft-deleted route

2. Route Search:
   - GET    /api/route-search/?origin=XXX&destination=YYY

3. GeoJSON Data:
   - GET    /api/airports/                   # All airports as GeoJSON
   - GET    /api/waypoints/                  # All waypoints as GeoJSON
   - GET    /api/fir-geojson/                # All FIR regions as GeoJSON

4. Calculations:
   - POST   /api/calculate-route/            # Calculate route distance/time
   - POST   /api/calculate-fuel/             # Calculate fuel requirements

FEATURES ADDED FOR DELETE FUNCTIONALITY:
1. Delete Route: DELETE /api/delete-route/<int:route_id>/
   - Permanently removes route from database
   - Returns: {'status': 'success', 'message': 'Route deleted successfully'}

2. Advanced Delete: DELETE /api/advanced-delete-route/<int:route_id>/
   - Supports soft delete (is_deleted flag)
   - Can be restored via /api/restore-route/<id>/
   - Accepts query parameter: ?type=soft or ?type=hard

3. Conflict Resolution in Save:
   - EnhancedSaveRouteAPI handles name conflicts
   - Returns conflict data when route name already exists
   - Provides options: overwrite, save_as, cancel
"""
