"""Tests for pagination logic."""

from __future__ import annotations


from pige.interfaces.gui.pagination import PaginationState, paginate_items


def test_pagination_state_total_pages():
    """Test total pages calculation."""
    state = PaginationState(page=1, page_size=10, total_items=95)
    assert state.total_pages == 10  # 95 items / 10 per page = 10 pages
    
    state = PaginationState(page=1, page_size=100, total_items=100)
    assert state.total_pages == 1
    
    state = PaginationState(page=1, page_size=50, total_items=150)
    assert state.total_pages == 3


def test_pagination_state_indices():
    """Test start and end indices."""
    state = PaginationState(page=1, page_size=10, total_items=100)
    assert state.start_index == 0
    assert state.end_index == 10
    
    state = PaginationState(page=2, page_size=10, total_items=100)
    assert state.start_index == 10
    assert state.end_index == 20
    
    # Last page with partial fill
    state = PaginationState(page=10, page_size=10, total_items=95)
    assert state.start_index == 90
    assert state.end_index == 95


def test_pagination_state_is_first_last():
    """Test first/last page detection."""
    state = PaginationState(page=1, page_size=10, total_items=100)
    assert state.is_first_page is True
    assert state.is_last_page is False
    
    state.page = 10
    assert state.is_first_page is False
    assert state.is_last_page is True
    
    state.page = 5
    assert state.is_first_page is False
    assert state.is_last_page is False


def test_pagination_state_get_page_slice():
    """Test getting page slice from list."""
    items = list(range(100))  # 0-99
    
    state = PaginationState(page=1, page_size=10, total_items=100)
    slice1 = state.get_page_slice(items)
    assert slice1 == list(range(0, 10))
    
    state.page = 2
    slice2 = state.get_page_slice(items)
    assert slice2 == list(range(10, 20))
    
    state.page = 10
    slice10 = state.get_page_slice(items)
    assert slice10 == list(range(90, 100))


def test_pagination_state_go_to_page():
    """Test navigation to specific page."""
    state = PaginationState(page=1, page_size=10, total_items=100)
    
    state.go_to_page(5)
    assert state.page == 5
    
    # Can't go beyond last page
    state.go_to_page(20)
    assert state.page == 10  # Clamped to max
    
    # Can't go before first page
    state.go_to_page(-5)
    assert state.page == 1  # Clamped to min


def test_pagination_state_next_previous():
    """Test next/previous navigation."""
    state = PaginationState(page=1, page_size=10, total_items=100)
    
    # Next from first page
    assert state.next_page() is True
    assert state.page == 2
    
    # Previous
    assert state.previous_page() is True
    assert state.page == 1
    
    # Can't go previous from first
    assert state.previous_page() is False
    assert state.page == 1
    
    # Go to last page
    state.page = 10
    assert state.next_page() is False  # Can't go beyond last
    assert state.page == 10


def test_pagination_state_set_page_size():
    """Test changing page size."""
    state = PaginationState(page=5, page_size=10, total_items=100)
    # Currently on page 5, showing items 40-49
    
    # Change to larger page size
    state.set_page_size(20)
    # Should try to keep item 40 visible
    # Item 40 is on page 3 with size 20 (pages: 1=0-19, 2=20-39, 3=40-59)
    assert state.page == 3
    assert state.page_size == 20
    
    # Change to smaller page size
    state.set_page_size(5)
    # Item at start of page 3 (with size 20) was 40
    # With size 5: 40 // 5 = 8, so page 9 (pages are 1-indexed)
    assert state.page == 9
    assert state.page_size == 5


def test_paginate_items_helper():
    """Test paginate_items helper function."""
    items = list(range(100))
    
    # Page 1
    page_items, state = paginate_items(items, page=1, page_size=10)
    assert page_items == list(range(0, 10))
    assert state.page == 1
    assert state.total_items == 100
    
    # Page 5
    page_items, state = paginate_items(items, page=5, page_size=10)
    assert page_items == list(range(40, 50))
    assert state.page == 5


def test_pagination_with_empty_list():
    """Test pagination with no items."""
    state = PaginationState(page=1, page_size=10, total_items=0)
    assert state.total_pages == 1  # At least 1 page even if empty
    assert state.start_index == 0
    assert state.end_index == 0
    assert state.is_first_page is True
    assert state.is_last_page is True
    
    items: list[int] = []
    slice_items = state.get_page_slice(items)
    assert slice_items == []


def test_pagination_with_small_dataset():
    """Test pagination when items fit in one page."""
    items = list(range(5))  # Only 5 items
    
    state = PaginationState(page=1, page_size=10, total_items=5)
    assert state.total_pages == 1
    assert state.is_first_page is True
    assert state.is_last_page is True
    
    slice_items = state.get_page_slice(items)
    assert slice_items == items


def test_pagination_edge_cases():
    """Test edge cases."""
    # Exactly divisible
    state = PaginationState(page=1, page_size=10, total_items=100)
    assert state.total_pages == 10
    
    # One extra item (needs extra page)
    state = PaginationState(page=1, page_size=10, total_items=101)
    assert state.total_pages == 11
    
    # Very large page size
    state = PaginationState(page=1, page_size=9999, total_items=100)
    assert state.total_pages == 1
    assert state.end_index == 100


def test_pagination_page_size_change_preserves_position():
    """Test that changing page size tries to preserve viewing position."""
    items = list(range(1000))
    
    # Start on page 10 with size 50 (viewing items 450-499)
    state = PaginationState(page=10, page_size=50, total_items=1000)
    old_start = state.start_index  # 450
    
    # Change to page size 100
    state.set_page_size(100)
    # Should now be on page 5 (items 400-499, which includes old item 450)
    assert state.page == 5
    new_start = state.start_index  # 400
    
    # Old start item should still be on current page
    assert old_start >= new_start
    assert old_start < state.end_index


def test_pagination_state_with_single_item():
    """Test pagination with just 1 item."""
    state = PaginationState(page=1, page_size=10, total_items=1)
    assert state.total_pages == 1
    assert state.start_index == 0
    assert state.end_index == 1
    
    items = ["only_item"]
    slice_items = state.get_page_slice(items)
    assert slice_items == ["only_item"]
