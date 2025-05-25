from django.contrib import admin
from django.urls import path, include, re_path
from django.conf.urls.static import static, serve
from django.conf import settings

API_VERSION = 'api/v1/'

urlpatterns = [
    # path('admin/', admin.site.urls),
    path(API_VERSION, include('acl.urls')),
    path(API_VERSION, include('api.urls')),
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    re_path(r'^static/(?P<path>.*)$', serve, {'document_root': settings.STATIC_ROOT}),

] 
urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)


if settings.DEBUG:
    adminurl = [
        path('admin/', admin.site.urls),
    ]
    urlpatterns += adminurl