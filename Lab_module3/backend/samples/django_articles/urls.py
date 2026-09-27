from django.urls import path

from . import views

urlpatterns = [
    path("articles/", views.list_articles),
    path("articles/<int:pk>/", views.article_detail),
    path("articles/new/", views.create_article),
]
