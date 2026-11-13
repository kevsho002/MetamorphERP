from django.urls import path

from apps.holidays import views

urlpatterns = [
    path("holidays/", views.HolidaysView.as_view(), name="holidays"),
    path("holidays/segments/", views.SegmentsView.as_view(), name="holiday-segments"),
    path("holidays/segments/generate/", views.GenerateView.as_view(), name="holiday-segments-generate"),
    path("holidays/<int:pk>/", views.HolidayDetailView.as_view(), name="holiday"),
]
