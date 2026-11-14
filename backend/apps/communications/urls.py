from django.urls import path

from apps.communications import views

urlpatterns = [
    path("announcements/", views.AnnouncementsView.as_view(), name="announcements"),
    path("announcements/pending/", views.PendingView.as_view(), name="announcements-pending"),
    path("announcements/compliance/", views.ComplianceSummaryView.as_view(), name="announcements-compliance"),
    path("announcements/<int:pk>/", views.AnnouncementDetailView.as_view(), name="announcement"),
    path("announcements/<int:pk>/publish/", views.PublishView.as_view(), name="announcement-publish"),
    path("announcements/<int:pk>/archive/", views.ArchiveView.as_view(), name="announcement-archive"),
    path("announcements/<int:pk>/ack/", views.AckView.as_view(), name="announcement-ack"),
    path("announcements/<int:pk>/compliance/", views.ComplianceView.as_view(), name="announcement-compliance"),
]
