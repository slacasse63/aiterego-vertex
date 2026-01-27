"""
hermes_modules/search_strategies/__init__.py - Exports des stratégies de recherche
"""

from .person import search_by_person
from .emotion import search_by_emotion
from .date import search_by_date
from .tags import search_by_tags

__all__ = [
    'search_by_person',
    'search_by_emotion', 
    'search_by_date',
    'search_by_tags'
]