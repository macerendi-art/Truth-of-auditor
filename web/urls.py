from django.urls import path

from . import admin_views, views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("set-toko/", views.set_toko, name="set_toko"),
    path("upload/", views.upload, name="upload"),
    path("transactions/", views.transactions, name="transactions"),
    path("reconcile/", views.reconcile, name="reconcile"),
    path("batch/<int:pk>/", views.batch_detail, name="batch_detail"),
    path("batch/<int:pk>/rematch/", views.rematch, name="rematch_batch"),
    path("run/<int:pk>/", views.run_detail, name="run_detail"),
    path("run/<int:pk>/export/", views.export_run, name="export_run"),
    path("result/<int:pk>/review/", views.review, name="review"),
    path("kelola/toko/", admin_views.kelola_toko, name="kelola_toko"),
    path("kelola/toko/<int:pk>/delete/", admin_views.delete_toko, name="delete_toko"),
    path("kelola/user/", admin_views.kelola_user, name="kelola_user"),
    path("kelola/user/<int:pk>/", admin_views.kelola_user_edit, name="kelola_user_edit"),
    path("kelola/user/<int:pk>/delete/", admin_views.delete_user, name="delete_user"),
    path("upload/bulk-delete/", admin_views.bulk_delete_uploads, name="bulk_delete_uploads"),
    path("upload/<int:pk>/delete/", admin_views.delete_upload, name="delete_upload"),
    path("batch/<int:pk>/delete/", admin_views.delete_batch, name="delete_batch"),
]
