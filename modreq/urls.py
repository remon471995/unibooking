from django.urls import path

from . import views

app_name = "modreq"

urlpatterns = [
    path("<int:pk>/approve/", views.approve, name="approve"),
    path("<int:pk>/return/", views.return_, name="return"),
]
