"""Tests for OSRM Car Profile"""

import pytest
from src.data.osrm_profile import CarProfile, get_car_profile


class TestCarProfile:
    """Test suite for CarProfile configuration"""
    
    @pytest.fixture
    def profile(self):
        """Create CarProfile instance for tests"""
        return get_car_profile()
    
    def test_highway_speeds(self, profile):
        """Test default highway speeds"""
        assert profile.get_speed('motorway') == 90
        assert profile.get_speed('primary') == 65
        assert profile.get_speed('residential') == 25
        assert profile.get_speed('service') == 15
        assert profile.get_speed('unknown_type') == 25  # default
    
    def test_maxspeed_override(self, profile):
        """Test maxspeed tag overrides profile speed"""
        # maxspeed lower than profile: use maxspeed
        assert profile.get_speed('motorway', maxspeed=70) == 70
        
        # maxspeed higher: cap at profile * (1 + tolerance)
        # 90 * 1.2 = 108
        assert profile.get_speed('motorway', maxspeed=150) == 108
        
        # maxspeed within tolerance: use maxspeed
        assert profile.get_speed('primary', maxspeed=70) == 70
    
    def test_service_penalties(self, profile):
        """Test service road penalties"""
        # Regular service road
        assert profile.get_speed('service') == 15
        
        # Parking service road (0.5x penalty)
        assert profile.get_speed('service', service='parking') == 7.5
        
        # Driveway (0.5x penalty)
        assert profile.get_speed('service', service='driveway') == 7.5
        
        # Unknown service type (no penalty)
        assert profile.get_speed('service', service='unknown') == 15
    
    def test_turn_penalties_straight(self, profile):
        """Test turn penalties for straight/slight turns"""
        # Straight (0-30°)
        assert profile.get_turn_penalty(0) == 0.0
        assert profile.get_turn_penalty(15) == 0.0
        assert profile.get_turn_penalty(29) == 0.0
        
        # Slight turn (30-60°)
        assert profile.get_turn_penalty(30) == 2.0
        assert profile.get_turn_penalty(45) == 2.0
        assert profile.get_turn_penalty(59) == 2.0
    
    def test_turn_penalties_normal(self, profile):
        """Test turn penalties for normal turns"""
        # Normal turn (60-120°)
        assert profile.get_turn_penalty(60) == 7.5
        assert profile.get_turn_penalty(90) == 7.5
        assert profile.get_turn_penalty(119) == 7.5
    
    def test_turn_penalties_sharp(self, profile):
        """Test turn penalties for sharp turns"""
        # Sharp turn (120-150°)
        assert profile.get_turn_penalty(120) == 12.0
        assert profile.get_turn_penalty(135) == 12.0
        assert profile.get_turn_penalty(149) == 12.0
    
    def test_turn_penalties_uturn(self, profile):
        """Test turn penalties for U-turns"""
        # U-turn on two-way road (150-180°)
        assert profile.get_turn_penalty(150) == 20.0
        assert profile.get_turn_penalty(170) == 20.0
        assert profile.get_turn_penalty(180) == 20.0
        
        # U-turn on oneway (impossible)
        penalty = profile.get_turn_penalty(170, is_oneway=True)
        assert penalty == float('inf')
        penalty = profile.get_turn_penalty(180, is_oneway=True)
        assert penalty == float('inf')
    
    def test_highway_allowed_basic(self, profile):
        """Test basic highway type filtering"""
        # Allowed types
        assert profile.is_highway_allowed('motorway', {})
        assert profile.is_highway_allowed('primary', {})
        assert profile.is_highway_allowed('residential', {})
        
        # Not allowed types
        assert not profile.is_highway_allowed('footway', {})
        assert not profile.is_highway_allowed('cycleway', {})
        assert not profile.is_highway_allowed('path', {})
    
    def test_highway_allowed_avoid_tags(self, profile):
        """Test highway filtering with avoid tags"""
        # Area tag blocks routing
        assert not profile.is_highway_allowed('primary', {'area': 'yes'})
        
        # Construction blocks routing
        assert not profile.is_highway_allowed(
            'motorway',
            {'construction': 'yes'}
        )
        
        # Proposed blocks routing
        assert not profile.is_highway_allowed(
            'trunk',
            {'proposed': 'yes'}
        )
    
    def test_highway_allowed_access_restrictions(self, profile):
        """Test highway filtering with access restrictions"""
        # Private access blocks routing
        assert not profile.is_highway_allowed(
            'residential',
            {'access': 'private'}
        )
        
        # No motorcar access
        assert not profile.is_highway_allowed(
            'primary',
            {'motorcar': 'no'}
        )
        
        # Emergency only
        assert not profile.is_highway_allowed(
            'service',
            {'access': 'emergency'}
        )
        
        # Delivery only
        assert not profile.is_highway_allowed(
            'residential',
            {'access': 'delivery'}
        )
    
    def test_lane_count(self):
        """Test lane count extraction"""
        # Explicit lanes
        assert CarProfile.get_lane_count({'lanes': '1'}) == 1
        assert CarProfile.get_lane_count({'lanes': '2'}) == 2
        assert CarProfile.get_lane_count({'lanes': '4'}) == 4
        
        # Default (no lanes tag)
        assert CarProfile.get_lane_count({}) == 1
        
        # Invalid lanes (default to 1)
        assert CarProfile.get_lane_count({'lanes': 'unknown'}) == 1
        assert CarProfile.get_lane_count({'lanes': ''}) == 1
        
        # Zero lanes (minimum 1)
        assert CarProfile.get_lane_count({'lanes': '0'}) == 1
    
    def test_parse_maxspeed(self, profile):
        """Test maxspeed parsing"""
        # Simple integer
        assert profile.parse_maxspeed('60') == 60
        assert profile.parse_maxspeed('90') == 90
        
        # With units
        assert profile.parse_maxspeed('50 kmh') == 50
        assert profile.parse_maxspeed('50 km/h') == 50
        assert profile.parse_maxspeed('30 mph') == 48  # ~48 km/h
        
        # Country-specific (Russia)
        assert profile.parse_maxspeed('ru:urban') == 60
        assert profile.parse_maxspeed('ru:motorway') == 110
        assert profile.parse_maxspeed('ru:living_street') == 20
        
        # No limit
        assert profile.parse_maxspeed('de:motorway') is None
        assert profile.parse_maxspeed('none') == 140
        
        # Invalid
        assert profile.parse_maxspeed('unknown') is None
        assert profile.parse_maxspeed('') is None
        assert profile.parse_maxspeed(None) is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
