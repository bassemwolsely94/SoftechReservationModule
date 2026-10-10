"""apps/gamification/urls.py — mounted at /api/gamification/"""
from django.urls import path

from . import views

urlpatterns = [
    path('me/',                 views.me,              name='gamification-me'),
    path('leaderboard/',        views.leaderboard,     name='gamification-leaderboard'),
    path('branches/',           views.branches,        name='gamification-branches'),
    path('rules/',              views.rules,           name='gamification-rules'),
    path('rules/<slug:key>/',   views.rule_detail,     name='gamification-rule-detail'),
    path('levels/',             views.levels,          name='gamification-levels'),
    path('levels/<int:number>/', views.level_detail,   name='gamification-level-detail'),
    path('badges/',             views.badges,          name='gamification-badges'),
    path('badges/<slug:key>/',  views.badge_detail,    name='gamification-badge-detail'),
    path('adjust/',             views.adjust,          name='gamification-adjust'),
    path('run/',                views.run_now,         name='gamification-run'),
    path('reports/overview/',   views.report_overview, name='gamification-report'),
    path('reports/export/',     views.report_export,   name='gamification-export'),
    path('changes/',            views.changes,         name='gamification-changes'),
]
