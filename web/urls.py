from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("set-toko/", views.set_toko, name="set_toko"),
    path("upload/", views.upload, name="upload"),
    path("transactions/", views.transactions, name="transactions"),
    path("reconcile/", views.reconcile, name="reconcile"),
    path("run/<int:pk>/", views.run_detail, name="run_detail"),
    path("run/<int:pk>/export/", views.export_run, name="export_run"),
    path("result/<int:pk>/review/", views.review, name="review"),
]
