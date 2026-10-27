from django.urls import path
from . import views

urlpatterns = [
    path('filter-options/',   views.filter_options,         name='analytics-filter-options'),
    path('sales/',            views.sales_overview,         name='analytics-sales'),
    path('customers/',        views.customer_analytics,     name='analytics-customers'),
    path('performance/',      views.performance_analytics,  name='analytics-performance'),
    path('inventory/',        views.inventory_analytics,    name='analytics-inventory'),
    path('customer-search/',  views.customer_search,        name='analytics-customer-search'),
    path('churn/',            views.customer_churn,         name='analytics-churn'),
    path('branch-contribution/', views.branch_contribution, name='analytics-branch-contribution'),
    path('inventory-investment/', views.inventory_investment, name='analytics-inventory-investment'),
]
