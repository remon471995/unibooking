from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("", views.audit_list, name="list"),
    path("card/<int:card_id>/", views.card_history, name="card_history"),
]
