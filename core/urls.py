from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from academia.authentication import CaptchaLoginView, LoginCodeView, LoginEmailView
from academia import views as academia_views

admin.site.site_header = 'Formación Técnica y Profesional EC'
admin.site.site_title = 'Sistema Académico'
admin.site.index_title = 'Panel de administración'

urlpatterns = [
    path('login/', CaptchaLoginView.as_view(), name='login'),
    path('login/correo/', LoginEmailView.as_view(), name='login_email'),
    path('login/codigo/', LoginCodeView.as_view(), name='login_code'),
    path('logout/', auth_views.LogoutView.as_view(next_page='/login/'), name='logout'),

    path('', academia_views.home, name='home'),

    path('admin/', admin.site.urls),

    path('', include('academia.urls')),
]
