from django.urls import path

from . import views

app_name = "customers"

urlpatterns = [
    path("", views.customer_list, name="list"),
    path("by-card/<int:card_id>/", views.customer_by_card, name="by_card"),
    path("lookup/", views.customer_lookup, name="lookup"),
    path("<str:key>/", views.customer_detail, name="detail"),
    path("<str:key>/update/", views.customer_update, name="update"),
]
