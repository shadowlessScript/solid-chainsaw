from rest_framework.routers import DefaultRouter
from api import views

router = DefaultRouter(trailing_slash=False)

router.register('foundation',views.FoundationViewSet, basename='foundation')
router.register('department',views.DepartmentViewSet, basename='department')
router.register('reports',views.ReportsViewSet, basename='reports')
router.register('analytics',views.AnalyticsViewSet, basename='analytics')
router.register('pims-projects', views.ProjectsViewSet, basename='pims-projects')
router.register("objectives", views.ProjectsGoals, basename="objectives")
router.register('proj-admin', views.WorkPlanViewSet, basename='proj-admin')
                         
urlpatterns = router.urls