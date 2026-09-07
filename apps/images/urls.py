from django.urls import path
from . import views

urlpatterns = [
    # Jobs
    path('jobs/',                   views.JobListCreateView.as_view(),  name='image-jobs'),
    path('jobs/bulk/',              views.bulk_create_jobs,             name='image-jobs-bulk'),
    path('jobs/revise-all/',        views.revise_all,                   name='image-jobs-revise-all'),
    path('jobs/<int:pk>/',          views.JobDetailView.as_view(),      name='image-job-detail'),
    path('jobs/<int:pk>/cancel/',   views.cancel_job,                   name='image-job-cancel'),

    # Candidates
    path('candidates/',                     views.CandidateListView.as_view(), name='image-candidates'),
    path('candidates/<int:pk>/review/',     views.review_candidate,            name='image-candidate-review'),
    path('candidates/<int:pk>/redownload/', views.redownload_candidate,        name='image-candidate-redownload'),

    # Product gallery management
    path('products/search/',                                    views.product_image_search, name='image-product-search'),
    path('products/<int:item_pk>/gallery/',                    views.product_gallery,   name='image-gallery'),
    path('products/<int:item_pk>/candidates/',                 views.item_candidates,   name='image-item-candidates'),
    path('products/<int:item_pk>/upload/',                     views.upload_product_image, name='image-upload'),
    path('products/<int:item_pk>/set-primary/<int:media_pk>/', views.set_primary_image, name='image-set-primary'),
    path('products/<int:item_pk>/reorder/',                    views.reorder_images,    name='image-reorder'),
    path('products/<int:item_pk>/images/<int:media_pk>/',      views.delete_image,      name='image-delete'),

    # Stats & meta
    path('report/',       views.images_report,    name='image-report'),
    path('review-queue/', views.review_queue,     name='image-review-queue'),
    path('filter-meta/',  views.filter_meta,      name='image-filter-meta'),
    path('insights/',     views.learning_insights, name='image-insights'),
]
