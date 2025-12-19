from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from airports.views import AirportGeoJSON

# ایجاد router برای ViewSet های REST Framework
router = DefaultRouter()
router.register(r'waypoints', views.WaypointViewSet)
router.register(r'airways', views.AirwayViewSet)
router.register(r'airway-segments', views.AirwaySegmentViewSet)
router.register(r'routes', views.RouteViewSet)
router.register(r'fir-regions', views.FlightInformationRegionViewSet)  # FIR اضافه شد

urlpatterns = [
    # ========== API های REST Framework (ViewSet ها) ==========
    path('api/', include(router.urls)),
    
    # ========== API های کاربردی برای Frontend ==========
    # این API ها برای Frontend موجود در base.html استفاده می‌شوند
    
    # داده‌های GeoJSON
    path('api/airports/', AirportGeoJSON.as_view(), name='airports_geojson'),
    path('api/waypoints/', views.WaypointGeoJSON.as_view(), name='waypoints_geojson'),
    path('api/fir-geojson/', views.FIRGeoJSON.as_view(), name='fir_geojson'),  # FIR GeoJSON
    
    # عملیات مسیریابی
    path('api/calculate-route/', views.CalculateRoute.as_view(), name='calculate_route'),
    path('api/save-route/', views.SaveRouteAPI.as_view(), name='save_route'),
    path('api/get-routes/', views.GetRoutesAPI.as_view(), name='get_routes'),
    path('api/delete-route/<int:route_id>/', views.DeleteRouteAPI.as_view(), name='delete_route'),
    path('api/import-route/', views.ImportRouteAPI.as_view(), name='import_route'),
    
    # ========== ROUTE SEARCH APIs ==========
    # API جستجوی مسیر - نسخه ساده (برای Frontend جدید)
    path('api/route-search/', views.RouteSearchAPI.as_view(), name='route_search_simple'),
    
    # API جستجوی مسیر - نسخه ViewSet (از طریق router)
    # دسترسی: GET /api/routes/search/?origin=OIII&destination=OIMM
    # (این endpoint از قبل در RouteViewSet وجود دارد و نیازی به اضافه کردن نیست)
    
    # API جستجوی مسیر بر اساس فرودگاه
    # دسترسی: GET /api/routes/search_by_airport/?airport=OIII
    # (این endpoint از قبل در RouteViewSet وجود دارد و نیازی به اضافه کردن نیست)
    
    # ========== DASHBOARD VIEW ==========
    path('dashboard/', views.dashboard_view, name='dashboard'),
    
    # ========== ROOT URL (برای تست) ==========
    path('', views.dashboard_view, name='home'),
]
